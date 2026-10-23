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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qlm_doc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(ROOT, "docs", "03-stdlib.md")
BEGIN = "<!-- api:begin -->"
END = "<!-- api:end -->"

DESC = {
    "std/aes.qma": "AES-128-GCM：分组加密（AES-NI 快路径 + T-table 降级）+ GHASH + CTR",
    "std/b64.qma": "base64 编解码",
    "std/blake2b.qma": "BLAKE2b（RFC 7693）密码学哈希 + keyed / 变长输出",
    "std/core.qma": "标量小工具",
    "std/crc64.qma": "CRC-64/XZ（ECMA-182 反射多项式，xz/zlib 容器的 64 位校验）",
    "std/cli.qma": "命令行 flag 解析（--k=v / --k v / -k v）",
    "std/deque.qma": "双端队列（两端 O(1) + 自动扩容）",
    "std/ds.qma": "环形缓冲与二叉最小堆",
    "std/gen.qma": "泛型算法库（min/max/clamp/dist/contains/index_of/reverse，调用点推导单态化）",
    "std/gzip.qma": "DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码",
    "std/hash.qma": "FNV-1a 32/64 非密码学哈希（缓存键 / 分片）",
    "std/hex.qma": "十六进制编解码",
    "std/http.qma": "HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商）",
    "std/httpc.qma": "HTTP/1.1 客户端核心：URL 拆分 / 请求构造 / 响应解析（content-length / chunked）/ 重定向判定（纯函数，零 socket 依赖）",
    "std/httpc_net.qma": "HTTP 客户端传输层：httpc_get / httpc_get_tls / httpc_get_follow（Windows；TLS 走 std/tls_net）",
    "std/regex.qma": "正则引擎（回溯 VM）：字面/./字符类/转义类/量词 *+?{n,m}/交替/分组(?:)/锚点 ^$；compile+match/full/exec/find/replace[_all]，步数上限防病态回溯",
    "std/json.qma": "DOM 式 JSON 解析与 builder",
    "std/log.qma": "分级日志（stdout）+ 结构化字段 + 级别过滤",
    "std/lru.qma": "LRU 缓存（开放寻址表 + 双向链表，单句柄 O(1)）",
    "std/md5.qma": "MD5（RFC 1321，仅兼容用途，不要用于密码）",
    "std/math.qma": "浮点与整数数学（exp/log/pow/sin/cos/atan/双曲/hypot + sqrt/cbrt/取整/gcd）",
    "std/mem.qma": "slab 分配 / fd 表 / 缓冲 / 对象池",
    "std/net.qma": "阻塞 TCP 便捷层",
    "std/rand.qma": "xorshift64* 伪随机",
    "std/serialize.qma": "LEB128 varint / 定长整数 / 长度前缀帧",
    "std/rsa.qma": "RSA PKCS#1 v1.5 / PSS 验签（SHA-256，证书链与 TLS 用）",
    "std/set.qma": "集合 set[int] / set[str]（map 支撑，含交并差）",
    "std/sha1.qma": "SHA-1",
    "std/sha256.qma": "SHA-256 + HMAC-SHA256",
    "std/sha512.qma": "SHA-512 / SHA-384（变体 IV 复用压缩函数）+ HMAC-SHA512",
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
    """公开函数签名列表（pub fn，显示剥 pub 前缀）。

    v1.47 起经 qlm_doc.scan_file：v1.43 把 std 全库改成 pub fn 后，
    旧实现只认行首 `fn `，把 271 个 pub API 全部漏出、反把 195 个内部
    函数列为"公开"——本轮修正（scan_file 的 /// 文档由 render 透出）。
    """
    return [d for d in qlm_doc.scan_file(path) if d.kind == "fn"]


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
    total = internal_total = 0
    for name, path in modules():
        fns = public_fns(path)
        _pub_n, internal_n = qlm_doc.fn_counts(path)
        total += len(fns)
        internal_total += internal_n
        parts.append(f"\n### `{name}`\n")
        parts.append(DESC[name])
        parts.append("")
        parts.append("```quelmara")
        if fns:
            for d in fns:
                # doc comment 原样透出为 ///（与源码写法一致）
                for para in d.doc:
                    parts.extend("/// " + ln if ln else "///" for ln in para)
                parts.append(d.signature)
        else:
            parts.append("// 无公开函数")
        parts.append("```")
    return "\n".join(parts), len(modules()), total, internal_total


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

    body, nmod, nfn, ninternal = render()
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{BEGIN}\n{body}\n{END}{tail}"

    # 同步模块数 / 公开函数数 / 内部函数数（§1 的引言句，整句重写）
    new = re.sub(
        r"^\d+ 个模块，\*\*\d+ 个公开函数\*\*.*$",
        f"{nmod} 个模块，**{nfn} 个公开函数**（另有 {ninternal} 个内部函数）",
        new, count=1, flags=re.M)

    if args.check:
        if new != text:
            print("FAIL：docs/03-stdlib.md 与 std/ 源码不一致，请运行 gen_stdlib_doc.py")
            return 1
        print(f"PASS：{nmod} 个模块 / {nfn} 个公开函数"
              f"（内部 {ninternal}），文档与源码一致")
        return 0

    if crlf:
        new = new.replace("\n", "\r\n")
    with open(DOC, "wb") as f:
        f.write(new.encode("utf-8"))
    print(f"已更新 {os.path.relpath(DOC, ROOT)}：{nmod} 个模块 / "
          f"{nfn} 个公开函数（内部 {ninternal}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
