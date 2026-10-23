#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 语言服务器（`quelmara lsp`）
=====================================
LSP 3.17 子集，**纯标准库、零外部依赖**，数据源是 `qlm_index.py` 的语义索引
（索引的设计口径与边界见那个模块的模块头）。

## 能力

| LSP 方法 | 说明 |
|---|---|
| `textDocument/completion` | 作用域内局部 → 本文件顶层 → 导入的 `pub` → 内建 → 关键字；`x.` 之后按类型给字段/方法/变体（含类型约束里的接口方法） |
| `textDocument/hover` | 签名 + 种类 + 声明上方的 `//` 注释 + 位置 |
| `textDocument/definition` | 本文件或 import 进来的 `pub` 声明 |
| `textDocument/references` | 本文件精确；顶层符号按需索引整个工作区 |
| `textDocument/prepareRename` / `rename` | 同上范围，非法标识符/关键字/内建直接拒绝 |
| `textDocument/documentSymbol` | 顶层声明 + 成员（字段/变体/方法）树 |
| `textDocument/documentHighlight` | 同符号在本文档内的出现 |
| `workspace/symbol` | 全工作区按名字子串查（首次调用会建全量索引） |
| `textDocument/publishDiagnostics` | 词法错误 / 括号不配对 / 顶层重名 |

## 协议口径

- **stdio 传输**，`Content-Length` 帧；默认 `positionEncoding = utf-16`（LSP 默认值）。
- 同步方式 **full**（`change: 1`）：每次 `didChange` 用整篇文本重建索引。
  一个文件 1–7 ms（见 `06-status.md` §3.9），比做增量 diff 简单且不会错。
- 未实现的方法返回 `-32601 MethodNotFound`，不静默吞掉（编辑器会显示错误而不是卡住）。
- 任何请求内部异常都返回 `-32603` 并带消息，**服务不退出**——编辑器插件崩掉比功能缺失更糟。

## 用法

```bash
python tools/stage0/qlm_cli.py lsp                 # 起服务（编辑器 stdio 连接）
python tools/stage0/qlm_cli.py lsp --index FILE    # 只索引并打印统计（性能口径）
python tools/stage0/qlm_cli.py lsp --check FILE    # 打印诊断，有错误退出码 1
```

编辑器侧（VS Code 为例）注册一个 `vscode-languageclient`，`command` 填
`python <repo>/tools/stage0/qlm_cli.py lsp`，`documentSelector` 用 `{ language: "quelmara" }`。
仓库不附插件：本模块只保证协议这一侧可被任意客户端驱动（`tests/lsp_test.py`
就是自己写的最小客户端）。
"""

import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlm import KEYWORDS, SRC_EXT  # noqa: E402
from qlm_index import (COMPLETION_KIND, SYMBOL_KIND, Workspace,  # noqa: E402
                       path_to_uri, summarize, uri_to_path)

SERVER_NAME = "quelmara-lsp"


def _ident_ok(name):
    if not name or name in KEYWORDS:
        return False
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in name)


class _RpcError(Exception):
    """处理器主动报错：`handle` 会把它翻成 JSON-RPC error 响应。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Server:
    def __init__(self, root=None, trace=False, stdin=None, stdout=None):
        self.ws = Workspace(root)
        self.trace = trace
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self.alive = True

    # ---- 传输 ----

    def _read(self):
        headers = {}
        while True:
            line = self.stdin.readline()
            if not line:
                return None
            line = line.decode("ascii", "replace").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        try:
            n = int(headers.get("content-length", "0"))
        except ValueError:
            return None
        if n <= 0:
            return None
        buf = b""
        while len(buf) < n:
            chunk = self.stdin.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        try:
            return json.loads(buf.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _send(self, obj):
        data = json.dumps(obj, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        self.stdout.write(b"Content-Length: %d\r\n\r\n" % len(data))
        self.stdout.write(data)
        self.stdout.flush()

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _err(self, mid, code, msg):
        self._send({"jsonrpc": "2.0", "id": mid,
                    "error": {"code": code, "message": msg}})

    # ---- 主循环 ----

    def run(self):
        while self.alive:
            msg = self._read()
            if msg is None:
                break
            if self.trace:
                sys.stderr.write(f"[lsp] <- {msg.get('method') or 'response'}\n")
                sys.stderr.flush()
            try:
                self.handle(msg)
            except Exception:
                mid = msg.get("id")
                if mid is not None:
                    self._err(mid, -32603,
                              "quelmara-lsp 内部错误："
                              + traceback.format_exc(limit=2).splitlines()[-1])
                elif self.trace:
                    traceback.print_exc()
        return 0

    def handle(self, msg):
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if method is None:                       # 客户端对我们请求的响应
            return
        if method == "exit":
            self.alive = False
            return
        handler = getattr(self, "on_" + method.replace("/", "_")
                          .replace("$", "dollar_"), None)
        if handler is None:
            if mid is not None:
                self._err(mid, -32601, f"未实现的方法：{method}")
            return
        try:
            result = handler(params)
        except _RpcError as e:
            if mid is not None:
                self._err(mid, e.code, str(e))
            return
        if mid is not None:
            self._send({"jsonrpc": "2.0", "id": mid, "result": result})

    # ---- 生命周期 ----

    def on_initialize(self, params):
        root = params.get("rootUri") or params.get("rootPath")
        if root:
            self.ws.root = (uri_to_path(root) if root.startswith("file:")
                            else root)
        return {
            "capabilities": {
                "positionEncoding": "utf-16",
                "textDocumentSync": {"openClose": True, "change": 1,
                                     "save": {"includeText": True}},
                "completionProvider": {"triggerCharacters": [".", ":", "@"],
                                       "resolveProvider": False},
                "hoverProvider": True,
                "definitionProvider": True,
                "referencesProvider": True,
                "documentHighlightProvider": True,
                "documentSymbolProvider": True,
                "workspaceSymbolProvider": True,
                "renameProvider": {"prepareProvider": True},
                "workspace": {"workspaceFolders": {"supported": False,
                                                   "changeNotifications": False}},
            },
            "serverInfo": {"name": SERVER_NAME, "version": _version()},
        }

    def on_initialized(self, params):
        return None

    def on_shutdown(self, params):
        return None

    # ---- 文档同步 ----

    def _index_of(self, params):
        td = params.get("textDocument") or {}
        uri = td.get("uri")
        if not uri:
            return None
        path = uri_to_path(uri)
        ix = self.ws.docs.get(path)
        if ix is None:
            ix = self.ws.index(path)
        return ix

    def _publish(self, ix):
        if ix is None:
            return
        self.notify("textDocument/publishDiagnostics",
                    {"uri": path_to_uri(ix.path), "diagnostics": ix.diagnostics()})

    def on_textDocument_didOpen(self, params):
        td = params.get("textDocument") or {}
        uri = td.get("uri")
        if not uri:
            return None
        ix = self.ws.index(uri_to_path(uri), td.get("text"), force=True)
        self._publish(ix)
        return None

    def on_textDocument_didChange(self, params):
        td = params.get("textDocument") or {}
        uri = td.get("uri")
        changes = params.get("contentChanges") or []
        if not uri or not changes:
            return None
        text = changes[-1].get("text")
        if text is None:
            return None
        ix = self.ws.index(uri_to_path(uri), text, force=True)
        self._publish(ix)
        return None

    def on_textDocument_didSave(self, params):
        ix = self._index_of(params)
        if ix is not None:
            self.ws.index(ix.path, force=True)
            self._publish(self.ws.docs[ix.path])
        return None

    def on_textDocument_didClose(self, params):
        td = params.get("textDocument") or {}
        if td.get("uri"):
            self.ws.drop(uri_to_path(td["uri"]))
        return None

    # ---- 查询 ----

    def _pos(self, ix, params):
        p = params.get("position") or {}
        line = int(p.get("line", 0))
        char = int(p.get("character", 0))
        return line, ix.lm.from_utf16(line, char)

    def on_textDocument_completion(self, params):
        ix = self._index_of(params)
        if ix is None:
            return {"isIncomplete": False, "items": []}
        line, col = self._pos(ix, params)
        items = []
        for rank, (name, kind, detail) in enumerate(ix.completions(line, col)):
            items.append({
                "label": name,
                "kind": COMPLETION_KIND.get(kind, 1),
                "detail": detail,
                "sortText": f"{rank:04d}",
                "insertText": name,
            })
        return {"isIncomplete": False, "items": items}

    def on_textDocument_hover(self, params):
        ix = self._index_of(params)
        if ix is None:
            return None
        line, col = self._pos(ix, params)
        occ = ix.occ_at(line, col)
        if occ is None:
            return None
        ref = occ.ref
        if ref is None:
            return {"contents": {"kind": "markdown",
                                 "value": f"`{occ.name}` · 未解析"
                                          "（索引没有足够类型信息，不猜）"}}
        if ref.kind == "builtin":
            return {"contents": {"kind": "markdown",
                                 "value": f"```quelmara\n{occ.name}\n```\n"
                                          "编译器内建（无源码位置）"}}
        if ref.kind == "ext":
            jx = self.ws.index(ref.path)
            s = next((x for x in jx.syms if x.off == ref.off), None) if jx else None
            if s is None:
                return None
            return {"contents": {"kind": "markdown",
                                 "value": jx.hover_text(s)}}
        s = ix.syms[ref.sid]
        return {"contents": {"kind": "markdown", "value": ix.hover_text(s)}}

    def _location(self, path, off, name):
        jx = self.ws.index(path)
        if jx is None:
            return None
        line, col = jx.lm.pos(off)
        return {"uri": path_to_uri(path),
                "range": {"start": {"line": line,
                                    "character": jx.lm.to_utf16(line, col)},
                          "end": {"line": line,
                                  "character": jx.lm.to_utf16(line, col + len(name))}}}

    def on_textDocument_definition(self, params):
        ix = self._index_of(params)
        if ix is None:
            return None
        line, col = self._pos(ix, params)
        occ = ix.occ_at(line, col)
        if occ is None or occ.ref is None or occ.ref.kind == "builtin":
            return None
        ref = occ.ref
        if ref.kind == "ext":
            loc = self._location(ref.path, ref.off, ref.name)
            return [loc] if loc else None
        s = ix.syms[ref.sid]
        return [{"uri": path_to_uri(s.path),
                 "range": {"start": {"line": s.line,
                                     "character": ix.lm.to_utf16(s.line, s.col)},
                           "end": {"line": s.line,
                                   "character": ix.lm.to_utf16(
                                       s.line, s.col + len(s.name))}}}]

    def _ref_locations(self, ix, occ, include_decl):
        ref = occ.ref
        if ref is None or ref.kind == "builtin":
            return []
        if ref.kind == "ext":
            hits = self.ws.find_refs(ref.path, ref.name, ref.symkind,
                                     include_decl)
        else:
            s = ix.syms[ref.sid]
            if s.container is None:
                hits = self.ws.find_refs(s.path, s.name, s.kind, include_decl)
            else:
                hits = [(ix.path, o.off, o.end) for o in ix.occs
                        if o.ref is not None and o.ref.kind == "local"
                        and o.ref.sid == s.sid
                        and (include_decl or o.off != s.off)]
        out = []
        for path, off, end in hits:
            jx = self.ws.index(path)
            if jx is None:
                continue
            line, col = jx.lm.pos(off)
            eline, ecol = jx.lm.pos(end)
            out.append({"uri": path_to_uri(path),
                        "range": {"start": {"line": line,
                                            "character": jx.lm.to_utf16(line, col)},
                                  "end": {"line": eline,
                                          "character": jx.lm.to_utf16(eline, ecol)}}})
        return out

    def on_textDocument_references(self, params):
        ix = self._index_of(params)
        if ix is None:
            return []
        line, col = self._pos(ix, params)
        occ = ix.occ_at(line, col)
        if occ is None:
            return []
        ctx = params.get("context") or {}
        return self._ref_locations(ix, occ, bool(ctx.get("includeDeclaration")))

    def on_textDocument_documentHighlight(self, params):
        ix = self._index_of(params)
        if ix is None:
            return []
        line, col = self._pos(ix, params)
        occ = ix.occ_at(line, col)
        if occ is None or occ.ref is None:
            return []
        ref = occ.ref
        out = []
        for o in ix.occs:
            if o.ref is None or o.ref.kind != ref.kind:
                continue
            if ref.kind == "local":
                if o.ref.sid != ref.sid:
                    continue
                kind = 3 if o.off == ix.syms[ref.sid].off else 1
            elif ref.kind == "ext":
                if o.ref.path != ref.path or o.ref.name != ref.name:
                    continue
                kind = 1
            else:
                continue
            l, c = ix.lm.pos(o.off)
            el, ec = ix.lm.pos(o.end)
            out.append({"range": {"start": {"line": l,
                                            "character": ix.lm.to_utf16(l, c)},
                                  "end": {"line": el,
                                          "character": ix.lm.to_utf16(el, ec)}},
                        "kind": kind})
        return out

    def on_textDocument_documentSymbol(self, params):
        ix = self._index_of(params)
        return ix.document_symbols() if ix else []

    def on_workspace_symbol(self, params):
        q = (params.get("query") or "").lower()
        self.ws.ensure_all()
        out = []
        for path, jx in sorted(self.ws.docs.items()):
            for s in jx.syms:
                if s.kind in ("local", "param", "type_param", "field",
                              "variant"):
                    continue
                if q and q not in s.name.lower():
                    continue
                out.append({"name": s.name,
                            "kind": SYMBOL_KIND.get(s.kind, 13),
                            "location": {"uri": path_to_uri(path),
                                         "range": jx.name_range(s)}})
                if len(out) >= 300:
                    return out
        return out

    # ---- 重命名 ----

    def on_textDocument_prepareRename(self, params):
        ix = self._index_of(params)
        if ix is None:
            return None
        line, col = self._pos(ix, params)
        occ = ix.occ_at(line, col)
        if occ is None or occ.ref is None or occ.ref.kind == "builtin":
            return None
        l, c = ix.lm.pos(occ.off)
        return {"range": {"start": {"line": l,
                                    "character": ix.lm.to_utf16(l, c)},
                          "end": {"line": l,
                                  "character": ix.lm.to_utf16(l, c + len(occ.name))}},
                "placeholder": occ.name}

    def on_textDocument_rename(self, params):
        ix = self._index_of(params)
        if ix is None:
            return None
        new = params.get("newName") or ""
        if not _ident_ok(new):
            raise _RpcError(-32602,
                            f"非法标识符：{new!r}（关键字，或含非法字符；"
                            "标识符须以字母/下划线开头）")
        line, col = self._pos(ix, params)
        occ = ix.occ_at(line, col)
        if occ is None or occ.ref is None or occ.ref.kind == "builtin":
            raise _RpcError(-32602,
                            "该位置不可重命名：没有解析到用户声明的符号"
                            "（编译器内建或类型未知）")
        edits = {}
        for loc in self._ref_locations(ix, occ, True):
            edits.setdefault(loc["uri"], []).append(
                {"range": loc["range"], "newText": new})
        # 字段改名：本文件里 `.name` 因接收者类型未知而没解析上的，若该字段名
        # 在本文件内唯一，一并改掉（否则改名后编译期报"字段不存在"，属于噪音）
        ref = occ.ref
        if ref.kind == "local":
            s = ix.syms[ref.sid]
            if s.kind == "field" and len(ix.field_by_name.get(s.name, [])) == 1:
                for o in ix.occs:
                    if o.ref is None and o.name == s.name:
                        l, c = ix.lm.pos(o.off)
                        edits.setdefault(path_to_uri(ix.path), []).append({
                            "range": {"start": {"line": l,
                                                "character": ix.lm.to_utf16(l, c)},
                                      "end": {"line": l,
                                              "character": ix.lm.to_utf16(
                                                  l, c + len(o.name))}},
                            "newText": new})
        for uri in edits:
            edits[uri].sort(key=lambda e: (e["range"]["start"]["line"],
                                           e["range"]["start"]["character"]),
                            reverse=True)
        return {"changes": edits}


def _version():
    try:
        from qlm_cli import VERSION
        return VERSION
    except Exception:
        return "0"


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------


def _print_diags(ix):
    diags = ix.diagnostics()
    for d in diags:
        line = d["range"]["start"]["line"] + 1
        col = d["range"]["start"]["character"] + 1
        sev = {1: "error", 2: "warning"}.get(d["severity"], "info")
        print(f"  {ix.path}:{line}:{col}: {sev}: {d['message']}")
    return diags


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="quelmara lsp",
        description="Quelmara 语言服务器（stdio JSON-RPC；也可用 --index 做离线索引）")
    ap.add_argument("--stdio", action="store_true",
                    help="标准输入输出传输（编辑器用；默认就是它）")
    ap.add_argument("--root", default=None, help="工作区根（默认当前目录）")
    ap.add_argument("--trace", action="store_true", help="把协议消息打到 stderr")
    ap.add_argument("--index", default=None, metavar="FILE",
                    help="只索引一个文件并打印统计（性能口径）")
    ap.add_argument("--symbols", default=None, metavar="FILE",
                    help="打印符号表")
    ap.add_argument("--at", default=None, metavar="FILE:LINE:COL",
                    help="打印该位置的解析结果")
    ap.add_argument("--completions", default=None, metavar="FILE:LINE:COL",
                    help="打印该位置的补全项")
    ap.add_argument("--check", default=None, metavar="FILE",
                    help="打印诊断；有 error 时退出码 1")
    args = ap.parse_args(argv)

    ws = Workspace(args.root or os.getcwd())

    if args.index:
        ix = ws.index(args.index)
        info = summarize(ix)
        print(f"{info['path']}")
        print(f"  符号 {info['symbols']}  引用 {info['occurrences']}"
              f"（已解析 {info['resolved']} / 未解析 {info['unresolved']}）"
              f"  索引 {info['build_ms']:.2f} ms")
        print("  " + "  ".join(f"{k}={v}" for k, v in sorted(info["kinds"].items())))
        return 0

    if args.symbols:
        ix = ws.index(args.symbols)
        for s in ix.syms:
            print(f"{s.line + 1:>5}:{s.col:<4} {s.kind:<10} {s.container or '':<12}"
                  f" {s.detail}")
        return 0

    if args.at or args.completions:
        spec = args.at or args.completions
        head, _, col_s = spec.rpartition(":")
        path, _, line_s = head.rpartition(":")
        if not path or not line_s.isdigit() or not col_s.isdigit():
            raise SystemExit("位置写法：FILE:LINE:COL（行从 1 起）")
        line, col = int(line_s) - 1, int(col_s)
        ix = ws.index(path)
        if args.completions:
            for name, kind, detail in ix.completions(line, col):
                print(f"  {name:<26} {kind:<10} {detail}")
            return 0
        occ = ix.occ_at(line, col)
        print(f"{occ.name} -> {occ.ref}" if occ else "（该位置没有名字）")
        return 0

    if args.check:
        ix = ws.index(args.check)
        diags = _print_diags(ix)
        if not diags:
            print(f"  {args.check}: 无诊断")
        return 1 if any(d["severity"] == 1 for d in diags) else 0

    return Server(args.root, args.trace).run()


if __name__ == "__main__":
    sys.exit(main())
