#!/usr/bin/env python3
"""Collect the canonical C benchmark checksums (authoritative).
Each .c prints lines then a 'T' line then ns. The checksum is everything
BEFORE the 'T' line, joined by newline. All other languages must match it
byte-for-byte or the differential gate fails the whole bench row."""
import os, subprocess, json, glob
HERE = os.path.join(os.path.dirname(__file__), "..", "..", "bench", "speed")
HERE = os.path.abspath(HERE)
cc = ["gcc", "-O2", "-I", os.path.join(HERE, "c")]
res = {}
for src in sorted(glob.glob(os.path.join(HERE, "c", "*.c"))):
    b = os.path.basename(src)[:-2]
    exe = f"/tmp/_c_{b}"
    r = subprocess.run(cc + ["-o", exe, src], capture_output=True, text=True)
    if r.returncode != 0:
        res[b] = "ERR:" + r.stderr.strip()[:120]; continue
    out = subprocess.run([exe], capture_output=True, text=True).stdout
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if "T" in lines:
        i = lines.index("T"); ck = "\n".join(lines[:i])
    else:
        ck = out.strip().splitlines()[0] if out.strip() else "NO_T"
    res[b] = ck
json.dump(res, open("/tmp/c_checksums.json", "w"))
ok = [k for k, v in res.items() if not str(v).startswith("ERR")]
print("collected", len(ok), "checksums")
