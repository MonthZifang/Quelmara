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
    "std/cli.qma": "命令行 flag 解析（--k=v / --k v / -k v）",
    "std/deque.qma": "双端队列（两端 O(1) + 自动扩容）",
    "std/ds.qma": "环形缓冲与二叉最小堆",
    "std/gzip.qma": "DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码",
    "std/hash.qma": "FNV-1a 32/64 非密码学哈希（缓存键 / 分片）",
    "std/hex.qma": "十六进制编解码",
    "std/http.qma": "HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商）",
    "std/json.qma": "DOM 式 JSON 解析与 builder",
    "std/log.qma": "分级日志（stdout）+ 结构化字段 + 级别过滤",
    "std/math.qma": "浮点与整数数学（sqrt/cbrt/floor/ceil/round/powi/gcd）",
    "std/mem.qma": "slab 分配 / fd 表 / 缓冲 / 对象池",
    "std/net.qma": "阻塞 TCP 便捷层",
    "std/rand.qma": "xorshift64* 伪随机",
    "std/serialize.qma": "LEB128 varint / 定长整数 / 长度前缀帧",
    "std/rsa.qma": "RSA PKCS#1 v1.5 / PSS 验签（SHA-256，证书链与 TLS 用）",
    "std/set.qma": "集合 set[int] / set[str]（map 支撑，含交并差）",
    "std/sha1.qma": "SHA-1",
    "std/sha256.qma": "SHA-256 + HMAC-SHA256",
    "std/sort.qma": "快速排序与有序性检查",
    "std/sse.qma": "Server-Sent Events 服务端",
    "std/str.qma": "字符串工具集",
    "std/sync.qma": "自旋锁 / Treiber 无锁栈 / WaitGroup",
    "std/time.qma": "时间便捷层",
    "std/timer.qma": "轮询式定时器（MinHeap 驱动）",
    "std/url.qma": "URL 解析 / query 取值 / 编码解码",
    "std/utf8.qma": "UTF-8 解码/编码/严格校验（RFC 3629）",
    "std/ws.qma": "WebSocket 服务端（RFC 6455）",
    "std/x25519.qma": "Curve25519 上的 X25519 密钥交换（RFC 7748，TLS ECDHE 地基）",
    "std/tls13.qma": "TLS 1.3 密钥调度（HKDF-Expand-Label）+ AEAD 记录层",
    "std/p256.qma": "NIST P-256 域运算 + ECDSA 验签（TLS 证书签名）",
    "std/x509.qma": "X.509 解析 + P-256 验签 + 证书链/有效期/域名校验",
    "std/tls_client.qma": "TLS 1.3 客户端握手核心 + 证书链入口（RFC 8448 逐字节）",
    "std/tls_net.qma": "TLS 1.3 网络层：TCP 建连 + 握手 + 应用数据（Windows）",
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


def undocumented():
    """std/ 下存在、但 DESC 没登记的模块——它们会被静默漏出文档。"""
    out = []
    base = os.path.join(ROOT, "std")
    for dp, _dn, fns in os.walk(base):
        for fn in fns:
            if not fn.endswith(".qma"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), ROOT).replace(os.sep, "/")
            if rel not in DESC:
                out.append(rel)
    return sorted(out)


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

    missing = undocumented()
    if missing:
        print("FAIL：以下 std 模块未在 DESC 登记，会被漏出文档：" + "、".join(missing))
        return 1

    raw = open(DOC, "rb").read()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
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

    if crlf:
        new = new.replace("\n", "\r\n")
    with open(DOC, "wb") as f:
        f.write(new.encode("utf-8"))
    print(f"已更新 {os.path.relpath(DOC, ROOT)}：{nmod} 个模块 / {nfn} 个公开函数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
