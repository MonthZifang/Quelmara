#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持久化 KV 的进程级回归（v1.101）
================================
`tests/t127_kv.qma` 在**一个进程内**验证 API 语义；这里补的是只有跨进程才能
测到的部分——**恢复路径**：

  1. 写入 5 条 → 关库 → 新进程重开：5 条都在
  2. **撕裂的尾巴**：把文件尾砍掉半条记录 → 重开只剩 4 条（最后一条丢弃）
     → 再写一条 → 重开 5 条，且被砍的那条不会复活
  3. **垃圾尾巴**：尾部追加 200 字节随机数据 → 重开仍是 5 条，写入后仍一致
  4. **格式对拍**：用 Python 独立解析磁盘格式，逐条重算 FNV-1a 64，
     与文件里的 hash 对齐（格式漂移会立刻红）
  5. 吞吐 / 重开耗时（只报告，不做阈值）

跑法：python tests/kv_test.py
"""

import os
import shutil
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
FIX_SRC = os.path.join(ROOT, "tests", "kv_fixture.qma")
FIX_EXE = os.path.join(ROOT, "build", "kv_fixture.exe")
DB = os.path.join(ROOT, "build", "_kvtest.db")

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def build_fixture():
    r = subprocess.run([sys.executable, CLI, "build", FIX_SRC, "--target", "win",
                        "-o", FIX_EXE], cwd=ROOT, capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0:
        bad(f"夹具构建失败：{(r.stdout + r.stderr)[-300:]}")
        return False
    return True


def run(mode, expect_rc=0):
    r = subprocess.run([FIX_EXE, DB, mode], cwd=ROOT, capture_output=True,
                       text=True, timeout=120)
    text = (r.stdout + r.stderr).strip()
    if r.returncode != expect_rc:
        bad(f"{mode}: 退出码 {r.returncode}（期望 {expect_rc}）{text[-160:]}")
        return False
    return True


def clean():
    for p in (DB, DB + ".tmp"):
        if os.path.exists(p):
            os.remove(p)


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def parse_db(path):
    """按文档口径独立解析：KV1 <klen> <vlen> <hash>\\n<key><val>。"""
    with open(path, "rb") as f:
        buf = f.read()
    out = []
    pos = 0
    while pos < len(buf):
        nl = buf.find(b"\n", pos)
        if nl < 0:
            break
        parts = buf[pos:nl].split(b" ")
        if len(parts) != 4 or parts[0] != b"KV1":
            break
        klen, vlen, want = int(parts[1]), int(parts[2]), int(parts[3])
        body = nl + 1
        vn = vlen if vlen > 0 else 0
        if body + klen + vn > len(buf):
            break
        key = buf[body:body + klen]
        val = buf[body + klen:body + klen + vn]
        src = key if vlen == -1 else key + val
        if (fnv1a64(src) & 0xFFFFFFFFFFFFFFFF) != (want & 0xFFFFFFFFFFFFFFFF):
            break
        out.append((key, val, vlen == -1))
        pos = body + klen + vn
    return out


def main():
    if os.name != "nt":
        print("  [SKIP] std/kv 走 Windows 文件 API（@ffi）")
        return 0
    if not build_fixture():
        print(f"\nKV: PASS={PASS} FAIL={FAIL}")
        return 1

    # ---- 1. 跨进程重开 ----
    clean()
    if run("seed") and run("verify5"):
        ok("5 条记录写入后，新进程重开全部可见")

    # ---- 2. 撕裂的尾巴 ----
    n = os.path.getsize(DB)
    with open(DB, "r+b") as f:
        f.truncate(n - 6)                      # 砍掉最后一条记录的半截
    if run("verify4"):
        ok("尾部半条记录被丢弃，前 4 条完好")
    if run("add") and run("verify5b"):
        ok("撕裂尾巴之后仍能追加，且下次重开一致")

    # ---- 3. 垃圾尾巴 ----
    clean()
    run("seed")
    with open(DB, "ab") as f:
        f.write(bytes(range(200)))             # 200 字节垃圾（含 \n 与 \0）
    if run("verify5"):
        ok("尾部垃圾不影响重放（5 条仍可见）")
    if run("add") and run("verify6"):
        ok("垃圾尾巴之后追加成功，重开一致")

    # ---- 4. 格式对拍 ----
    clean()
    run("seed")
    recs = parse_db(DB)
    ok(f"Python 独立解析出 {len(recs)} 条记录") if len(recs) == 5 else \
        bad(f"格式解析得到 {len(recs)} 条（期望 5）")
    keys = [k for k, _v, _t in recs]
    ok("格式解析出的键顺序 = k0..k4") if keys == [b"k0", b"k1", b"k2", b"k3", b"k4"] \
        else bad(f"键序不符：{keys}")
    # parse_db 遇到 hash 不符就停：能解析出 5 条 = 每条 hash 都对。
    # 再钉住 FNV-1a 64 的两个标准向量，防止"两边一起错"。
    ok("FNV-1a 64 标准向量（空串 / 'a'）") if (
        fnv1a64(b"") == 0xCBF29CE484222325 and
        fnv1a64(b"a") == 0xAF63DC4C8601EC8C) else bad("FNV-1a 64 实现与标准不符")
    ok("每条记录的 hash 都能通过校验（否则解析会提前停）") if len(recs) == 5 \
        else bad("hash 校验失败")

    # 删除后应当出现墓碑记录（vlen = -1）
    run("add")
    recs = parse_db(DB)
    ok("追加后的记录数 6") if len(recs) == 6 else bad(f"记录数 {len(recs)}（期望 6）")

    # ---- 5. 吞吐 / 重开 ----
    clean()
    t0 = time.perf_counter()
    run("seed")
    seed_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    run("verify5")
    open_ms = (time.perf_counter() - t0) * 1000.0
    print(f"  [info] 5 条写入 + 关库（含进程启动）{seed_ms:.0f} ms；"
          f"重开 + 校验 {open_ms:.0f} ms；文件 {os.path.getsize(DB)} B")

    print(f"\nKV: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
