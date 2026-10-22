#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 std/ 源码重新生成 docs/03-stdlib.md 的 API 段。

文档里的函数清单是**生成物**，不要手改：改了库就跑这个脚本。

用法：
    python tools/dev/gen_stdlib_doc.py            # 原地更新
    python tools/dev/gen_stdlib_doc.py --check    # 只检查是否与源码一致（CI 可用）
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(ROOT, "docs", "03-stdlib.md")
BEGIN = "<!-- api:begin -->"
END = "<!-- api:end -->"

DESC = {
    "std/aes.qma": "AES-128-GCM：分组加密 + GHASH + CTR",
    "std/b64.qma": "base64 编解码",
    "std/core.qma": "标量小工具",
    "std/ds.qma": "环形缓冲与二叉最小堆",
    "std/gzip.qma": "DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码",
    "std/hex.qma": "十六进制编解码",
    "std/http.qma": "HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商）",
    "std/json.qma": "DOM 式 JSON 解析与 builder",
    "std/log.qma": "分级日志（stdout）+ 结构化字段 + 级别过滤",
    "std/math.qma": "浮点与整数数学（sqrt/cbrt/floor/ceil/round/powi/gcd）",
    "std/mem.qma": "slab 分配 / fd 表 / 缓冲 / 对象池",
    "std/net.qma": "阻塞 TCP 便捷层",
    "std/rand.qma": "xorshift64* 伪随机",
    "std/serialize.qma": "LEB128 varint / 定长整数 / 长度前缀帧",
    "std/sha1.qma": "SHA-1",
    "std/sha256.qma": "SHA-256 + HMAC-SHA256",
    "std/sort.qma": "快速排序与有序性检查",
    "std/sse.qma": "Server-Sent Events 服务端",
    "std/str.qma": "字符串工具集",
    "std/sync.qma": "自旋锁 / Treiber 无锁栈 / WaitGroup",
    "std/time.qma": "时间便捷层",
    "std/timer.qma": "轮询式定时器（MinHeap 驱动）",
    "std/url.qma": "URL 解析 / query 取值 / 编码解码",
    "std/ws.qma": "WebSocket 服务端（RFC 6455）",
    "std/net/core.qma": "连接槽位层（IOCP reactor 的底座）",
    "std/net/udp.qma": "UDP 封装与地址解析",
}


def modules():
    """按固定顺序返回 (相对路径, 绝对路径)。"""
    out = []
    for name in sorted(DESC):
        p = os.path.join(ROOT, name.replace("/", os.sep))
        if os.path.isfile(p):
            out.append((name, p))
    return out


def public_fns(path):
    fns = []
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.startswith("fn ") and not re.match(r"fn _", line):
            fns.append(re.sub(r"\s+", " ", line.rstrip("{").strip()))
    return fns


def render():
    parts = []
    total = 0
    for name, path in modules():
        fns = public_fns(path)
        total += len(fns)
        parts.append(f"\n### `{name}`\n")
        parts.append(DESC[name])
        parts.append("")
        parts.append("```quelmara")
        parts.extend(fns if fns else ["// 无公开函数"])
        parts.append("```")
    return "\n".join(parts), len(modules()), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不写回")
    args = ap.parse_args()

    text = open(DOC, encoding="utf-8").read()
    if BEGIN not in text or END not in text:
        print(f"FAIL：{DOC} 缺少 {BEGIN} / {END} 标记")
        return 1

    body, nmod, nfn = render()
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{BEGIN}\n{body}\n{END}{tail}"

    # 同步模块数与函数数（§1 的引言句）
    new = re.sub(r"\d+ 个模块，\*\*\d+ 个公开函数\*\*",
                 f"{nmod} 个模块，**{nfn} 个公开函数**", new, count=1)

    if args.check:
        if new != text:
            print("FAIL：docs/03-stdlib.md 与 std/ 源码不一致，请运行 gen_stdlib_doc.py")
            return 1
        print(f"PASS：{nmod} 个模块 / {nfn} 个公开函数，文档与源码一致")
        return 0

    with open(DOC, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"已更新 {os.path.relpath(DOC, ROOT)}：{nmod} 个模块 / {nfn} 个公开函数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
