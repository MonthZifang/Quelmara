#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能回归门禁自测（v1.86）。

门禁脚本本身也要被门禁：一个"永远绿"的性能门禁比没有门禁更糟——它会让
人以为有人在看。本测试逐条钉住它的四种行为：

  1. `--update` 能建基线（协议解析成功、七个指标都在）
  2. `--check` 对刚建的基线判 PASS（同一份产物，必须无回归）
  3. 把基线改成"快一倍" → 必须判 FAIL 且退出码 1（时间回归抓得到）
  4. 把基线校验和改坏 → 必须判 FAIL（"算错了"优先于"变快了"）
  5. 把基线体积改小 → 必须判 FAIL（体积是确定性指标，不看时间）

跑法：python tests/bench_gate_test.py
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "tools", "dev", "bench_gate.py")

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def want(cond, msg, detail=""):
    ok(msg) if cond else bad(f"{msg}{('（' + detail + '）') if detail else ''}")


def gate(baseline, *extra):
    cmd = [sys.executable, GATE, "--baseline", baseline] + list(extra)
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)


def main():
    target = "win" if os.name == "nt" else "native"
    tmp = tempfile.mkdtemp(prefix="qlm_gate_")
    base = os.path.join(tmp, "baseline.json")

    # ---- 1. 建基线 ----
    r = gate(base, "--update", "--target", target, "--repeat", "3")
    out = r.stdout + r.stderr
    want(r.returncode == 0, "建基线退出码 0", out[-300:])
    if not os.path.isfile(base):
        bad("基线文件未生成")
        print(f"\nBENCH_GATE: PASS={PASS} FAIL={FAIL}")
        return 1
    data = json.load(open(base, encoding="utf-8"))
    key = next(iter(data["entries"]))
    entry = data["entries"][key]
    want(len(entry["metrics"]) == 6, "基线含 6 个形状", str(list(entry["metrics"])))
    want(bool(entry["digest"]), "基线含校验和", entry["digest"])
    want(entry["size"] > 0, "基线含产物体积", str(entry["size"]))

    # ---- 2. 同一产物对基线判 PASS ----
    r = gate(base, "--check", "--target", target, "--repeat", "3")
    out = r.stdout + r.stderr
    want(r.returncode == 0, "同产物 --check 退出码 0", out[-300:])
    want("PASS：无回归" in out, "同产物判定 PASS")

    # ---- 3. 基线谎报"快一倍" → 必须失败 ----
    fast = json.loads(json.dumps(data))
    for m in fast["entries"][key]["metrics"].values():
        m["ns"] = max(1, m["ns"] // 2)
    p_fast = os.path.join(tmp, "fast.json")
    json.dump(fast, open(p_fast, "w", encoding="utf-8"))
    r = gate(p_fast, "--check", "--target", target, "--repeat", "1", "--no-noise")
    out = r.stdout + r.stderr
    want(r.returncode == 1, "谎报 2× 的基线判失败（退出码 1）", out[-300:])
    want("FAIL 回归" in out, "谎报 2× 时给出「FAIL 回归」")

    # ---- 4. 校验和不同 → 必须失败（先于时间判定） ----
    bad_digest = json.loads(json.dumps(data))
    bad_digest["entries"][key]["digest"] = "1"
    p_dig = os.path.join(tmp, "digest.json")
    json.dump(bad_digest, open(p_dig, "w", encoding="utf-8"))
    r = gate(p_dig, "--check", "--target", target, "--repeat", "1", "--no-noise")
    out = r.stdout + r.stderr
    want(r.returncode == 1, "校验和不一致判失败", out[-300:])
    want("校验和不一致" in out, "校验和不一致时给出明确原因")

    # ---- 5. 体积增长超阈值 → 必须失败 ----
    small = json.loads(json.dumps(data))
    small["entries"][key]["size"] = max(1, small["entries"][key]["size"] // 2)
    p_size = os.path.join(tmp, "size.json")
    json.dump(small, open(p_size, "w", encoding="utf-8"))
    r = gate(p_size, "--check", "--target", target, "--repeat", "1", "--no-noise")
    out = r.stdout + r.stderr
    want(r.returncode == 1, "体积增长判失败", out[-300:])
    want("体积" in out and "FAIL" in out, "体积超阈值时给出明确原因")

    print(f"\nBENCH_GATE: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
